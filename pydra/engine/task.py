# -*- coding: utf-8 -*-
"""task.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1RRV1gHbGJs49qQB1q1d5tQEycVRtuhw6

## Notes:

### Environment specs
1. neurodocker json
2. singularity file+hash
3. docker hash
4. conda env
5. niceman config
6. environment variables

### Monitors/Audit
1. internal monitor
2. external monitor
3. callbacks

### Resuming
1. internal tracking
2. external tracking (DMTCP)

### Provenance
1. Local fragments
2. Remote server

### Isolation
1. Working directory
2. File (copy to local on write)
3. read only file system
"""


import cloudpickle as cp
import dataclasses as dc
import inspect
import typing as ty

from .node import Node
from ..utils.messenger import AuditFlag
from .specs import (
    BaseSpec,
    SpecInfo,
    ShellSpec,
    ShellOutSpec,
    ContainerSpec,
    DockerSpec,
    SingularitySpec,
)
from .helpers import ensure_list


class BaseTask(Node):
    """This is a base class for Task objects.
    """

    _task_version: ty.Optional[
        str
    ] = None  # Task writers encouraged to define and increment when implementation changes sufficiently


class FunctionTask(BaseTask):
    def __init__(
        self,
        func: ty.Callable,
        output_spec: ty.Optional[BaseSpec] = None,
        name=None,
        splitter=None,
        combiner=None,
        audit_flags: AuditFlag = AuditFlag.NONE,
        messengers=None,
        messenger_args=None,
        cache_dir=None,
        **kwargs
    ):
        self.input_spec = SpecInfo(
            name="Inputs",
            fields=[
                (val.name, val.annotation, val.default)
                if val.default is not inspect.Signature.empty
                else (val.name, val.annotation)
                for val in inspect.signature(func).parameters.values()
            ]
            + [("_func", str, cp.dumps(func))],
            bases=(BaseSpec,),
        )
        if name is None:
            name = func.__name__
        super(FunctionTask, self).__init__(
            name,
            inputs=kwargs,
            splitter=splitter,
            combiner=combiner,
            audit_flags=audit_flags,
            messengers=messengers,
            messenger_args=messenger_args,
            cache_dir=cache_dir
        )
        if output_spec is None:
            if "return" not in func.__annotations__:
                output_spec = SpecInfo(
                    name="Output", fields=[("out", ty.Any)], bases=(BaseSpec,)
                )
            else:
                return_info = func.__annotations__["return"]
                if hasattr(return_info, "__name__"):
                    output_spec = SpecInfo(
                        name=return_info.__name__,
                        fields=list(return_info.__annotations__.items()),
                        bases=(BaseSpec,),
                    )
                # Objects like int, float, list, tuple, and dict do not have __name__ attribute.
                else:
                    if hasattr(return_info, "__annotations__"):
                        output_spec = SpecInfo(
                            name="Output",
                            fields=list(return_info.__annotations__.items()),
                            bases=(BaseSpec,),
                        )
                    else:
                        output_spec = SpecInfo(
                            name="Output",
                            fields=[
                                ("out{}".format(n + 1), t)
                                for n, t in enumerate(return_info)
                            ],
                            bases=(BaseSpec,),
                        )
        elif "return" in func.__annotations__:
            raise NotImplementedError("Branch not implemented")
        self.output_spec = output_spec
        self.set_output_keys()

    def _run_task(self):
        inputs = dc.asdict(self.inputs)
        del inputs["_func"]
        self.output_ = None
        output = cp.loads(self.inputs._func)(**inputs)
        if not isinstance(output, tuple):
            output = (output,)
        self.output_ = list(output)

    def _list_outputs(self):
        return self.output_


def to_task(func_to_decorate):
    def create_func(**original_kwargs):
        function_task = FunctionTask(func=func_to_decorate, **original_kwargs)
        return function_task

    return create_func


class ShellCommandTask(BaseTask):
    def __init__(
        self,
        name,
        input_spec: ty.Optional[SpecInfo] = None,
        output_spec: ty.Optional[SpecInfo] = None,
        audit_flags: AuditFlag = AuditFlag.NONE,
        messengers=None,
        messenger_args=None,
        cache_dir=None,
        **kwargs
    ):
        if input_spec is None:
            field = dc.field(default_factory=list)
            field.metadata = {}
            fields = [("args", ty.List[str], field)]
            input_spec = SpecInfo(name="Inputs", fields=fields, bases=(ShellSpec,))
        self.input_spec = input_spec
        super(ShellCommandTask, self).__init__(
            name=name,
            inputs=kwargs,
            audit_flags=audit_flags,
            messengers=messengers,
            messenger_args=messenger_args,
            cache_dir=cache_dir,
        )
        if output_spec is None:
            output_spec = SpecInfo(name="Output", fields=[], bases=(ShellOutSpec,))
        self.output_spec = output_spec

    @property
    def command_args(self):
        args = []
        for f in dc.fields(self.inputs):
            if f.name not in ["executable", "args"]:
                continue
            value = getattr(self.inputs, f.name)
            if value is not None:
                args.extend(ensure_list(value))
        return args

    @command_args.setter
    def command_args(self, args: ty.Dict):
        self.inputs = dc.replace(self.inputs, **args)

    @property
    def cmdline(self):
        return " ".join(self.command_args)

    def _run_task(self):
        self.output_ = None
        args = self.command_args
        if args:
            self.output_ = execute(args)

    def _list_outputs(self):
        return list(self.output_)


class ContainerTask(ShellCommandTask):
    def __init__(
        self,
        name,
        input_spec: ty.Optional[ContainerSpec] = None,
        output_spec: ty.Optional[ShellOutSpec] = None,
        audit_flags: AuditFlag = AuditFlag.NONE,
        messengers=None,
        messenger_args=None,
        cache_dir=None,
        **kwargs
    ):

        if input_spec is None:
            field = dc.field(default_factory=list)
            field.metadata = {}
            fields = [("args", ty.List[str], field)]
            input_spec = SpecInfo(name="Inputs", fields=fields, bases=(ContainerSpec,))
        super(ContainerTask, self).__init__(
            name=name,
            input_spec=input_spec,
            audit_flags=audit_flags,
            messengers=messengers,
            messenger_args=messenger_args,
            cache_dir=cache_dir,
            **kwargs
        )

    @property
    def cmdline(self):
        return " ".join(self.container_args + self.command_args)

    @property
    def container_args(self):
        if self.inputs.container is None:
            raise AttributeError("Container software is not specified")
        cargs = [self.inputs.container, "run"]
        if self.inputs.container_xargs is not None:
            cargs.extend(self.inputs.container_xargs)
        if self.inputs.image is None:
            raise AttributeError("Container image is not specified")
        cargs.append(self.inputs.image)
        return cargs

    def binds(self, opt):
        """Specify mounts to bind from local filesystems to container

        `bindings` are tuples of (local path, container path, bind mode)
        """
        bargs = []
        for binding in self.inputs.bindings:
            lpath, cpath, mode = binding
            if mode is None:
                mode = "rw"  # default
            bargs.extend([opt, "{0}:{1}:{2}".format(lpath, cpath, mode)])
        return bargs

    def _run_task(self):
        self.output_ = None
        args = self.container_args + self.command_args
        if args:
            self.output_ = execute(args)


class DockerTask(ContainerTask):
    def __init__(
        self,
        name,
        input_spec: ty.Optional[ContainerSpec] = None,
        output_spec: ty.Optional[ShellOutSpec] = None,
        audit_flags: AuditFlag = AuditFlag.NONE,
        messengers=None,
        messenger_args=None,
        cache_dir=None,
        **kwargs
    ):
        if input_spec is None:
            field = dc.field(default_factory=list)
            field.metadata = {}
            fields = [("args", ty.List[str], field)]
            input_spec = SpecInfo(name="Inputs", fields=fields, bases=(DockerSpec,))
        super(ContainerTask, self).__init__(
            name=name,
            input_spec=input_spec,
            audit_flags=audit_flags,
            messengers=messengers,
            messenger_args=messenger_args,
            cache_dir=cache_dir,
            **kwargs
        )

    @property
    def container_args(self):
        cargs = super().container_args
        assert self.inputs.container == "docker"
        if self.inputs.bindings:
            # insert bindings before image
            idx = len(cargs) - 1
            cargs[idx:-1] = self.binds("-v")
        return cargs


class SingularityTask(ContainerTask):
    def __init__(
        self,
        input_spec: ty.Optional[ContainerSpec] = None,
        output_spec: ty.Optional[ShellOutSpec] = None,
        audit_flags: AuditFlag = AuditFlag.NONE,
        messengers=None,
        messenger_args=None,
        cache_dir=None,
        **kwargs
    ):
        if input_spec is None:
            field = dc.field(default_factory=list)
            field.metadata = {}
            fields = [("args", ty.List[str], field)]
            input_spec = SpecInfo(
                name="Inputs", fields=fields, bases=(SingularitySpec,)
            )
        super(ContainerTask, self).__init__(
            input_spec=input_spec,
            audit_flags=audit_flags,
            messengers=messengers,
            messenger_args=messenger_args,
            cache_dir=cache_dir,
            **kwargs
        )

    @property
    def container_args(self):
        cargs = super().container_args
        assert self.inputs.container == "singularity"
        if self.inputs.bindings:
            # insert bindings before image
            idx = len(cargs) - 1
            cargs[idx:-1] = self.binds("-B")
        return cargs
